import argparse
import csv
import os

import cv2
import numpy as np
from mtcnn import MTCNN

import src.database as database
from .FaceRecogniser import Classifier
from .FaceAligner import FaceAligner
from .SORT.sort import Sort
from .utils import utils, uri_utils, media_fragment
from .utils.face_utils import judge_side_face

colours = np.random.rand(32, 3)

file_to_be_close = []


def export_frame(input_frame, d, classname, frame_num, frames_path):
    frame = input_frame.copy()
    cv2.rectangle(frame, (d[0], d[1]), (d[2], d[3]), colours[d[4] % 32, :] * 255, 3)
    cv2.putText(frame, classname, (d[0] - 10, d[1] - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                colours[d[4] % 32, :] * 255, 2)

    # print([str(i) for i in d] + [classname, str(frame_num)])

    filename = 'frame' + str(frame_num) + '.jpg'
    cv2.imwrite(os.path.join(frames_path, filename), frame)


def init_csv(path, fieldnames):
    file = open(path, 'w')
    writer = csv.writer(file, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(fieldnames)
    file_to_be_close.append(file)
    return writer


def parse_fragment(fragment, fps):
    frag = media_fragment.t_parser(fragment)
    return frag['startNormalized'] * fps, frag['endNormalized'] * fps


def main(video_path, project='general', video_speedup=25, export_frames=False, fragment=None, video_id=None):
    cluster_features = True

    if not video_id:
        video_id = video_path
    video_capture = cv2.VideoCapture(video_path)

    # setup all paths
    output_path = utils.generate_output_path('./data/out', project, video_id)
    cluster_path = os.path.join(output_path, 'cluster')
    frames_path = os.path.join(output_path, 'frames')
    if export_frames:
        os.makedirs(frames_path, exist_ok=True)
    classifier_path = os.path.join('data/classifier', project + '.pkl')
    trackers_csv = os.path.join(output_path, 'trackers.csv')
    predictions_csv = os.path.join(output_path, 'predictions.csv')

    # init csv outputs
    trackers_writer = init_csv(trackers_csv, ['x1', 'y1', 'x2', 'y2', 'track_id', 'frame'])
    predictions_writer = init_csv(predictions_csv, ['x1', 'y1', 'x2', 'y2', 'track_id', 'name',
                                                    'confidence', 'frame', 'tracker_sample', 'npt'])

    classifier = Classifier(classifier_path)
    classifier.collect_features = cluster_features
    aligner = FaceAligner(desiredFaceWidth=160, margin=10)

    detector = MTCNN(min_face_size=25)

    # init tracker
    tracker = Sort(min_hits=0)

    # frames per second
    fps = video_capture.get(cv2.CAP_PROP_FPS)
    video_length = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(video_capture.get(cv2.CAP_PROP_FRAME_WIDTH))

    scale_rate = 0.9 if width > 700 else 1

    frame_start = 0
    frame_end = video_length
    if fragment is not None:
        frame_start, frame_end = parse_fragment(fragment, fps)

    matches = []
    # iterate over the frames
    for frame_no in np.arange(frame_start, frame_end, video_speedup):
        print('frame %d/%d' % (frame_no, frame_end))
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, frame_no)

        # read the frame
        ret, frame = video_capture.retrieve()

        if frame is None:
            raise RuntimeError

        face_list = []
        attribute_list = []
        frame = cv2.resize(frame, (0, 0), fx=scale_rate, fy=scale_rate)
        frame_height, frame_width, _ = frame.shape
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rgb_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_GRAY2RGB)
        img_size = np.asarray(frame.shape)[0:2]
        bounding_boxes = detector.detect_faces(rgb_frame)

        # print('Detected %d faces' % len(bounding_boxes))
        for item in bounding_boxes:
            bb = utils.xywh2rect(*utils.fix_box(item['box']))
            face_list.append(bb)

            # use 5 face landmarks to judge the face is front or side
            facial_landmarks = list(item['keypoints'].values())
            dist_rate, high_ratio_variance, width_rate = judge_side_face(facial_landmarks)
            # dist_rate 0 => front face ; 1 => side face

            # face cropped
            cropped = frame.copy()[bb[1]:bb[3], bb[0]:bb[2], :]

            attribute_list.append([cropped, item['confidence'], dist_rate, high_ratio_variance, width_rate])

        trackers = tracker.update(np.array(face_list), img_size, cluster_path, attribute_list, rgb_frame)
        tracker_sample = tracker.frame_count
        # this is a counter of the frame analysed by the tracker (so normalised respect to the video_speedup)

        for d in trackers:
            d = d.astype(int)
            # the predicted position is outside the image
            if any(i < 0 for i in d) \
                    or d[0] >= frame_width or d[2] >= frame_width \
                    or d[1] >= frame_height or d[3] >= frame_height:
                print('Error tracker %d at frame %d:' % (d[4], frame_no))
                continue

            trackers_writer.writerow([str(i) for i in d] + [str(frame_no)])

            # cutting the img on the face
            trackers_cropped = aligner.align(frame[d[1]:d[3], d[0]:d[2], :])

            boxname = str(frame_no) + "_" + str(d[0]) + "_" + str(d[1]) + "_" + str(d[2]) + "_" + str(d[3])
            best_name, best_prob = classifier.predict_best(trackers_cropped, boxname)

            npt = utils.frame2npt(frame_no, fps)
            predictions_writer.writerow(
                [str(i) for i in d] + [best_name, best_prob, str(frame_no), tracker_sample, npt])

            # apply back the scale rate
            box = [x / scale_rate for x in d[0:4].tolist()]
            match = {
                'name': best_name,
                'project': project,
                'track_id': int(d[4]),
                'frame': int(frame_no),
                'confidence': best_prob,
                'tracker_sample': tracker_sample,
                'npt': npt,
                'locator': video_id,
                'bounding': utils.rect2xywh(*box),
                'rect': box
            }
            matches.append(match)
            if database.is_on():
                database.insert_partial_analysis(match)

            if export_frames:
                export_frame(frame, d, best_name, frame_no, frames_path)

    # TODO final track

    if database.is_on():
        print('COMPLETE')
        database.save_status(video_id, project, 'COMPLETE')

    for f in file_to_be_close:
        f.close()

    if cluster_features:
        clus = classifier.cluster_features(5, 3, 4)
        print(clus)

    return matches


def parse_args():
    """Parse input arguments."""
    parser = argparse.ArgumentParser()

    # files required in input
    parser.add_argument('-v', '--video', type=str, required=True,
                        help='Path or URI of the video to be analysed.')
    parser.add_argument('--project', type=str, default='general',
                        help='Name of the collection to be part of')

    # parameters
    parser.add_argument('--video_speedup', type=int, default=25,
                        help='Speed up for the video')
    parser.add_argument('--export_frames', default=False, action='store_true',
                        help='If specified, export the annotated frames')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    video = uri_utils.normalize_video(args.video)

    main(video, args.project, args.video_speedup, args.export_frames)
