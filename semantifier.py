from uuid import uuid5 as UUID, NAMESPACE_DNS
from rdflib import Graph, URIRef, Literal, Namespace, RDF
from rdflib.namespace import DCTERMS, XSD

EBUCORE = Namespace('http://www.ebu.ch/metadata/ontologies/ebucore/ebucore#')
NIF = Namespace('http://persistence.uni-leipzig.org/nlp2rdf/ontologies/nif-core#')
MEMAD = Namespace('https://memad.eu/ontology#')
OA = Namespace('https://www.w3.org/ns/oa#')
a = RDF['type']

EURECOM = URIRef('http://data.memad.eu/organization/EURECOM')
EURECOM_FACEREC = Literal('EURECOM Face Recognition')


def init_graph():
    g = Graph()

    # set prefixes
    g.namespace_manager.bind('ebucore', EBUCORE)
    g.namespace_manager.bind('nif', NIF)
    g.namespace_manager.bind('memad', MEMAD)
    g.namespace_manager.bind('oa', OA)
    g.namespace_manager.bind('dcterms', DCTERMS)

    return g


def semantify(res):
    data = res['results']
    video_id = res['video']
    timestamp = res['time']
    g = init_graph()

    if 'info' in res:
        info = res['info']
        video = URIRef(info['media']['value'])
        programme = URIRef(info['programme']['value'])

        g.add((programme, EBUCORE['isInstantiatedBy'], video))
    else:
        video = URIRef(video_id)

    for d in data:
        npt = d['npt']
        x = d['bounding']['x']
        y = d['bounding']['y']
        w = d['bounding']['w']
        h = d['bounding']['h']

        # uuid = UUID('%s%f%d%d%d%d' % (video_id, npt, x, y, w, h))
        frag_uri = video + '#t=npt:%f&xywh=%d,%d,%d,%d' % (npt, x, y, w, h)
        frag = URIRef(frag_uri)
        uuid = UUID(NAMESPACE_DNS, frag_uri)
        body = URIRef('http://data.memad.eu/identification/%s/person-identification/%s' % (video_id, uuid))

        g.add((frag, a, EBUCORE['MediaFragment']))
        g.add((frag, EBUCORE['isMediaFragmentOf'], video))

        g.add((body, a, NIF['Annotation']))
        g.add((body, a, MEMAD['VisualPersonIdentification']))
        g.add((body, RDF['value'], Literal(d['name'])))
        g.add((body, NIF['taIdentProv'], EURECOM_FACEREC))
        g.add((body, NIF['taIdentConf'], Literal(d['confidence'], datatype=XSD['decimal'])))

        annotation = URIRef('http://data.memad.eu/annotation/video-annotation/%s' % uuid)

        g.add((annotation, a, OA['Annotation']))
        g.add((annotation, DCTERMS['creator'], EURECOM))
        g.add((annotation, DCTERMS['created'], Literal(timestamp, datatype=XSD['datetime'])))
        g.add((annotation, DCTERMS['motivatedBy'], OA['identifying']))
        g.add((annotation, OA['hasTarget'], frag))
        g.add((annotation, OA['hasBody'], body))

    return g.serialize(format="turtle")
