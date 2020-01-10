"""An example of how to use your own dataset to train a classifier that recognizes people.
"""
# MIT License
#
# Copyright (c) 2016 David Sandberg
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys
import csv
import math
import pickle
import argparse
import numpy as np
import tensorflow.compat.v1 as tf
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import precision_recall_fscore_support
from sklearn.linear_model import LogisticRegression
from .utils import facenet


def main(mode, classifier='KNN', data_dir='data/training_img_aligned', model_path='model/20180402-114759.pb',
         classifier_path='classifier/classifier.pkl', use_split_dataset=False,
         test_data_dir=None, batch_size=90, image_size=160, seed=666, min_nrof_images_per_class=20,
         nrof_train_images_per_class=10):
    with tf.Graph().as_default():

        with tf.Session() as sess:

            np.random.seed(seed=seed)
            embedding_dir = "data/embedding/"
            os.makedirs(embedding_dir, exist_ok=True)

            if use_split_dataset:
                dataset_tmp = facenet.get_dataset(data_dir)
                train_set, test_set = split_dataset(dataset_tmp, min_nrof_images_per_class, nrof_train_images_per_class)
                if mode == 'TRAIN':
                    dataset = train_set
                elif mode == 'CLASSIFY':
                    dataset = test_set
            else:
                dataset = facenet.get_dataset(data_dir)

            # Check that there are at least one training image per class
            for cls in dataset:
                assert len(cls.image_paths) > 0, 'There must be at least one image for each class in the dataset'

            paths, labels = facenet.get_image_paths_and_labels(dataset)
            # Create a new label list containing names instead of numbers
            class_names = [cls.name.replace('_', ' ') for cls in dataset]
            label_name = [class_names[i] for i in labels]

            print('Number of classes: %d' % len(dataset))
            print('Number of images: %d' % len(paths))

            # Load the model
            print('Loading feature extraction model')
            facenet.load_model(model_path)

            # Get input and output tensors
            images_placeholder = tf.get_default_graph().get_tensor_by_name("input:0")
            embeddings = tf.get_default_graph().get_tensor_by_name("embeddings:0")
            phase_train_placeholder = tf.get_default_graph().get_tensor_by_name("phase_train:0")
            embedding_size = embeddings.get_shape()[1]
            print(embedding_size)

            # Run forward pass to calculate embeddings
            print('Calculating features for images')
            nrof_images = len(paths)
            nrof_batches_per_epoch = int(math.ceil(1.0 * nrof_images / batch_size))
            emb_array = np.zeros((nrof_images, embedding_size))
            for i in range(nrof_batches_per_epoch):
                start_index = i * batch_size
                end_index = min((i + 1) * batch_size, nrof_images)
                paths_batch = paths[start_index:end_index]
                images = facenet.load_data(paths_batch, False, False, image_size)
                feed_dict = {images_placeholder: images, phase_train_placeholder: False}
                emb_array[start_index:end_index, :] = sess.run(embeddings, feed_dict=feed_dict)
            # Store embedding and labels
            np.savetxt(embedding_dir + 'embedding.csv', emb_array, delimiter=",")
            with open(embedding_dir + 'label.csv', 'w') as f:
                writer = csv.writer(f)
                writer.writerows(zip(labels, paths))

            classifier_filename_exp = os.path.expanduser(classifier_path)
            os.makedirs(os.path.dirname(classifier_filename_exp), exist_ok=True)

            if mode == 'TRAIN':
                # Train classifier
                print('Training classifier')
                if classifier == 'SVM':
                    model = SVC(kernel='linear', probability=True)
                elif classifier == 'KNN':
                    model = KNeighborsClassifier(n_neighbors=1)
                elif classifier == 'Softmax':
                    model = LogisticRegression(random_state=0, solver='lbfgs', multi_class='multinomial')
                else:
                    model = RandomForestClassifier(n_estimators=1000, max_leaf_nodes=100, n_jobs=-1)
                model.fit(emb_array, labels)
                # Create a list of class names
                class_names = [cls.name.replace('_', ' ') for cls in dataset]

                # Saving classifier model
                with open(classifier_filename_exp, 'wb') as outfile:
                    pickle.dump((model, class_names), outfile)
                print('Saved classifier model to file "%s"' % classifier_filename_exp)

            elif mode == 'CLASSIFY':
                # Classify images
                print('Testing classifier')
                with open(classifier_filename_exp, 'rb') as infile:
                    (model, class_names) = pickle.load(infile)

                print('Loaded classifier model from file "%s"' % classifier_filename_exp)

                predictions = model.predict_proba(emb_array)
                best_class_indices = np.argmax(predictions, axis=1)
                best_class_probabilities = predictions[np.arange(len(best_class_indices)), best_class_indices]

                for i in range(len(best_class_indices)):
                    print('%4d  %s: %.3f' % (i, class_names[best_class_indices[i]], best_class_probabilities[i]))

                accuracy = np.mean(np.equal(best_class_indices, labels))
                report = precision_recall_fscore_support(labels, best_class_indices, average='weighted')
                print(report[2])
                print('Accuracy: %.3f' % accuracy)


def split_dataset(dataset, min_nrof_images_per_class, nrof_train_images_per_class):
    train_set = []
    test_set = []
    for cls in dataset:
        paths = cls.image_paths
        # Remove classes with less than min_nrof_images_per_class
        if len(paths) >= min_nrof_images_per_class:
            np.random.shuffle(paths)
            train_set.append(facenet.ImageClass(cls.name, paths[:nrof_train_images_per_class]))
            test_set.append(facenet.ImageClass(cls.name, paths[nrof_train_images_per_class:]))
    return train_set, test_set


def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='mode', help="Mode")
    train_parser = subparsers.add_parser('TRAIN', help="Train a new classifier.")
    train_parser.add_argument('--classifier', type=str,
                              choices=['KNN', 'SVM', 'RF', 'Softmax'],
                              help='The type of classifier to use.',
                              default='KNN')
    subparsers.add_parser('CLASSIFY', help='Predict whose image from trained classifier.')
    parser.add_argument('--data_dir', type=str, default='data/training_img_aligned',
                        help='Path to the data directory containing aligned LFW face patches.')
    parser.add_argument('--classifier_path', type=str, default='classifier/classifier.pkl',
                        help='Path to the KNN classifier')
    parser.add_argument('--model_path', type=str, default='model/20180402-114759.pb',
                        help='Path to the facenet embedding model')
    parser.add_argument('--use_split_dataset',
                        help='Indicates that the dataset specified by data_dir should be split '
                             'into a training and test set.' +
                             'Otherwise a separate test set can be specified using the test_data_dir option.',
                        action='store_true')
    parser.add_argument('--test_data_dir', type=str,
                        help='Path to the test data directory containing aligned images used for testing.')
    parser.add_argument('--batch_size', type=int,
                        help='Number of images to process in a batch.', default=90)
    parser.add_argument('--image_size', type=int,
                        help='Image size (height, width) in pixels.', default=160)
    parser.add_argument('--seed', type=int,
                        help='Random seed.', default=666)
    parser.add_argument('--min_nrof_images_per_class', type=int,
                        help='Only include classes with at least this number of images in the dataset', default=20)
    parser.add_argument('--nrof_train_images_per_class', type=int,
                        help='Use this number of images from each class for training and the rest for testing',
                        default=10)

    return parser.parse_args(argv)


if __name__ == '__main__':
    args = parse_arguments(sys.argv[1:])
    main(args.mode, args.classifier, args.data_dir, args.model_path, args.classifier_path, args.use_split_dataset,
         args.test_data_dir, args.batch_size, args.image_size, args.seed, args.min_nrof_images_per_class,
         args.nrof_train_images_per_class)