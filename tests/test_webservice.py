# Copyright 2016 Netherlands eScience Center
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import absolute_import

import pytest
from flask import make_response
from rdkit.Chem.AllChem import MolFromSmiles, Mol
import requests_mock
from werkzeug.exceptions import NotFound

from kripodb.webservice import server
from kripodb.pairs import open_similarity_matrix
from kripodb.version import __version__
from kripodb.webservice.client import WebserviceClient
from kripodb.webservice.server import KripodbJSONEncoder


class TestKripodbJSONEncoder(object):
    def test_mol(self):
        encoder = KripodbJSONEncoder()
        obj = MolFromSmiles('[*]C1OC(COP(=O)([O-])OP(=O)([O-])OCC2OC(N3C=CCC(C(N)=O)=C3)C(O)C2O)C(O)C1[*]')
        result = encoder.default(obj)
        assert result.decode().endswith('END\n')


@pytest.fixture
def similarity_matrix():
    matrix = open_similarity_matrix('data/similarities.frozen.h5')
    yield matrix
    matrix.close()


@pytest.fixture
def fragsdb_filename():
    return 'data/fragments.sqlite'


@pytest.fixture
def app(similarity_matrix, fragsdb_filename):
    return server.wsgi_app(similarity_matrix, fragsdb_filename)


class TestWebservice(object):
    def test_get_similar_fragments(self, app):
        fragment_id = '3j7u_NDP_frag24'
        cutoff = 0.85

        with app.app.test_request_context():
            result = server.get_similar_fragments(fragment_id, cutoff, 1000)
            expected = [
                {'query_frag_id': '3j7u_NDP_frag24', 'hit_frag_id': '3j7u_NDP_frag23', 'score': 0.8991},
            ]
        assert result == expected

    def test_get_similar_fragments_notfound(self, app):
        fragment_id = 'foo-bar'
        cutoff = 0.85

        with pytest.raises(NotFound) as cm:
            with app.app.test_request_context():
                server.get_similar_fragments(fragment_id, cutoff, 1000)
        assert 'foo-bar' in cm.value.description

    def test_get_fragments__fragid(self, app):
        fragment_id = '3j7u_NDP_frag24'

        with app.app.test_request_context():
            result = server.get_fragments(fragment_ids=[fragment_id])
            # Remove RDKit mol as equals is to strict
            del result[0]['mol']
            expected = [
                {'smiles': '[*]C1OC(COP(=O)([O-])OP(=O)([O-])OCC2OC(N3C=CCC(C(N)=O)=C3)C(O)C2O)C(O)C1[*]',
                 'pdb_code': '3j7u',
                 'pdb_title': 'Catalase structure determined by electron crystallography of thin 3D crystals',
                 'atom_codes': 'PA,O1A,O2A,O5B,C5B,C4B,O4B,C3B,O3B,C2B,C1B,O3,PN,O1N,O2N,O5D,C5D,C4D,O4D,C3D,O3D,C2D,O2D,C1D,N1N,C2N,C3N,C7N,O7N,N7N,C4N,C5N,C6N',
                 'uniprot_acc': 'P00432',
                 'prot_chain': 'A', 'het_seq_nr': 602, 'het_code': 'NDP', 'prot_name': 'Catalase',
                 'ec_number': '1.11.1.6', 'frag_nr': 24, 'frag_id': '3j7u_NDP_frag24', 'rowid': 7059,
                 'uniprot_name': 'Catalase', 'nr_r_groups': 2, 'het_chain': 'A', 'hash_code': '6ef5a609fb192dba'}
            ]
            assert result == expected

    def test_get_fragments__fragid_notfound(self, app):
        fragment_id = 'foo-bar'
        with app.app.test_request_context():
            with pytest.raises(NotFound) as cm:
                server.get_fragments(fragment_ids=[fragment_id])
            assert 'foo-bar' in cm.value.description

    def test_get_fragments__pdbcode(self, app):
        pdb_code = '3j7u'

        with app.app.test_request_context():
            result = server.get_fragments(pdb_codes=[pdb_code])
            assert len(result) == 32

    def test_get_fragments__pdbcode_notfound(self, app):
        pdb_code = 'foo-bar'
        with pytest.raises(NotFound) as cm:
            with app.app.test_request_context():
                server.get_fragments(pdb_codes=[pdb_code])
        assert 'foo-bar' in cm.value.description

    def test_get_version(self):
        result = server.get_version()

        expected = {'version': __version__}
        assert result == expected

    def test_wsgi_app(self, similarity_matrix, fragsdb_filename, app):
        assert app.app.config['matrix'] == similarity_matrix
        assert app.app.config['db_fn'] == fragsdb_filename
        assert app.app.json_encoder == KripodbJSONEncoder

    def test_get_fragment_svg(self, app):
        fragment_id = '3j7u_NDP_frag24'
        with app.app.test_request_context():
            result = server.get_fragment_svg(fragment_id, 400, 150)
            assert 'NH' in result
            assert '400' in result
            assert '150' in result

    def test_get_fragment_svg_notfound(self, app):
        fragment_id = 'foo-bar'
        with app.app.test_request_context():
            r = server.get_fragment_svg(fragment_id, 400, 150)
        assert r.status == []


@pytest.fixture
def base_url():
    return 'http://localhost:8084/kripo'


@pytest.fixture
def client(base_url):
    return WebserviceClient(base_url)


class TestWebServiceClient(object):
    def test_similar_fragments(self, base_url, client):
        with requests_mock.mock() as m:
            expected = [
                {'query_frag_id': '3j7u_NDP_frag24', 'hit_frag_id': '3j7u_NDP_frag23', 'score': 0.8991},
            ]
            url = base_url + '/fragments/3j7u_NDP_frag24/similar?cutoff=0.75&limit=1'
            m.get(url, json=expected)

            response = client.similar_fragments(fragment_id='3j7u_NDP_frag24', cutoff=0.75, limit=1)

            assert response == expected

    def test_fragments_by_id(self, base_url, client):
        with requests_mock.mock() as m:
            expected = [
                {'smiles': '[*]C1OC(COP(=O)([O-])OP(=O)([O-])OCC2OC(N3C=CCC(C(N)=O)=C3)C(O)C2O)C(O)C1[*]',
                 'pdb_code': '3j7u',
                 'pdb_title': 'Catalase structure determined by electron crystallography of thin 3D crystals',
                 'atom_codes': 'PA,O1A,O2A,O5B,C5B,C4B,O4B,C3B,O3B,C2B,C1B,O3,PN,O1N,O2N,O5D,C5D,C4D,O4D,C3D,O3D,C2D,O2D,C1D,N1N,C2N,C3N,C7N,O7N,N7N,C4N,C5N,C6N',
                 'uniprot_acc': 'P00432',
                 'mol': '3j7u_NDP_frag24\n     RDKit          3D\n\n 35 37  0  0  0  0  0  0  0  0999 V2000\n  -15.1410  -11.1250  -79.4200 P   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.6900  -10.9960  -80.8600 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -16.5040  -11.6890  -79.0770 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.9990   -9.6870  -78.7060 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.1870   -8.4550  -79.4050 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.6700   -7.3160  -78.5260 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -13.2400   -7.2390  -78.5880 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.2130   -5.9510  -78.9460 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -16.1600   -5.4570  -77.9880 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.0000   -5.0420  -79.0650 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.1790   -3.8250  -78.3260 R   0  0  0  0  0  1  0  0  0  0  0  0\n  -12.8370   -5.8690  -78.5180 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.5470   -5.6210  -79.2410 R   0  0  0  0  0  1  0  0  0  0  0  0\n  -14.0270  -11.9960  -78.6490 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.1810  -13.5930  -78.4870 P   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.5480  -14.2030  -79.8230 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.0330  -13.8500  -77.2690 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -12.6800  -14.0730  -78.1770 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -12.1840  -14.2350  -76.8490 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.1340  -13.1670  -76.6050 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.6880  -11.8550  -76.6770 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -10.5070  -13.2750  -75.2350 C   0  0  0  0  0  0  0  0  0  0  0  0\n   -9.4070  -14.1780  -75.3000 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -10.0970  -11.8400  -74.9280 C   0  0  0  0  0  0  0  0  0  0  0  0\n   -8.6920  -11.6460  -75.1050 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -10.8280  -10.9760  -75.9460 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.5890   -9.8540  -75.3660 N   0  0  0  0  0  0  0  0  0  0  0  0\n  -12.7860  -10.0630  -74.7850 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -13.5340   -9.0090  -74.2510 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.8620   -9.2740  -73.5990 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.1890  -10.4300  -73.3940 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.6600   -8.2650  -73.2400 N   0  0  0  0  0  0  0  0  0  0  0  0\n  -13.0230   -7.5870  -74.3390 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.7130   -7.4960  -74.9740 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.0640   -8.6200  -75.4710 C   0  0  0  0  0  0  0  0  0  0  0  0\n  1  2  2  0\n  1  3  1  0\n  1  4  1  0\n  1 14  1  0\n  4  5  1  0\n  5  6  1  0\n  6  7  1  0\n  6  8  1  0\n  7 12  1  0\n  8  9  1  0\n  8 10  1  0\n 10 11  1  0\n 10 12  1  0\n 12 13  1  0\n 14 15  1  0\n 15 16  2  0\n 15 17  1  0\n 15 18  1  0\n 18 19  1  0\n 19 20  1  0\n 20 21  1  0\n 20 22  1  0\n 21 26  1  0\n 22 23  1  0\n 22 24  1  0\n 24 25  1  0\n 24 26  1  0\n 26 27  1  0\n 27 28  1  0\n 27 35  1  0\n 28 29  2  0\n 29 30  1  0\n 29 33  1  0\n 30 31  2  0\n 30 32  1  0\n 33 34  1  0\n 34 35  2  0\nM  CHG  2   3  -1  17  -1\nM  END\n',
                 'prot_chain': 'A', 'het_seq_nr': 602, 'het_code': 'NDP', 'prot_name': 'Catalase',
                 'ec_number': '1.11.1.6', 'frag_nr': 24, 'frag_id': '3j7u_NDP_frag24', 'rowid': 7059,
                 'uniprot_name': 'Catalase', 'nr_r_groups': 2, 'het_chain': 'A', 'hash_code': '6ef5a609fb192dba'}
            ]
            url = base_url + '/fragments?fragment_ids=3j7u_NDP_frag24,3j7u_NDP_frag23'
            m.get(url, json=expected)

            response = client.fragments_by_id(fragment_ids=['3j7u_NDP_frag24', '3j7u_NDP_frag23'])

            assert isinstance(response[0]['mol'], Mol)
            del response[0]['mol']
            del expected[0]['mol']
            assert response == expected

    def test_fragments_by_pdb_codes(self, base_url, client):
        with requests_mock.mock() as m:
            molblock = '3j7u_NDP_frag24\n     RDKit          3D\n\n 35 37  0  0  0  0  0  0  0  0999 V2000\n  -15.1410  -11.1250  -79.4200 P   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.6900  -10.9960  -80.8600 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -16.5040  -11.6890  -79.0770 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.9990   -9.6870  -78.7060 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.1870   -8.4550  -79.4050 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.6700   -7.3160  -78.5260 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -13.2400   -7.2390  -78.5880 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.2130   -5.9510  -78.9460 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -16.1600   -5.4570  -77.9880 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.0000   -5.0420  -79.0650 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.1790   -3.8250  -78.3260 R   0  0  0  0  0  1  0  0  0  0  0  0\n  -12.8370   -5.8690  -78.5180 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.5470   -5.6210  -79.2410 R   0  0  0  0  0  1  0  0  0  0  0  0\n  -14.0270  -11.9960  -78.6490 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.1810  -13.5930  -78.4870 P   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.5480  -14.2030  -79.8230 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.0330  -13.8500  -77.2690 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -12.6800  -14.0730  -78.1770 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -12.1840  -14.2350  -76.8490 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.1340  -13.1670  -76.6050 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.6880  -11.8550  -76.6770 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -10.5070  -13.2750  -75.2350 C   0  0  0  0  0  0  0  0  0  0  0  0\n   -9.4070  -14.1780  -75.3000 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -10.0970  -11.8400  -74.9280 C   0  0  0  0  0  0  0  0  0  0  0  0\n   -8.6920  -11.6460  -75.1050 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -10.8280  -10.9760  -75.9460 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.5890   -9.8540  -75.3660 N   0  0  0  0  0  0  0  0  0  0  0  0\n  -12.7860  -10.0630  -74.7850 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -13.5340   -9.0090  -74.2510 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -14.8620   -9.2740  -73.5990 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.1890  -10.4300  -73.3940 O   0  0  0  0  0  0  0  0  0  0  0  0\n  -15.6600   -8.2650  -73.2400 N   0  0  0  0  0  0  0  0  0  0  0  0\n  -13.0230   -7.5870  -74.3390 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.7130   -7.4960  -74.9740 C   0  0  0  0  0  0  0  0  0  0  0  0\n  -11.0640   -8.6200  -75.4710 C   0  0  0  0  0  0  0  0  0  0  0  0\n  1  2  2  0\n  1  3  1  0\n  1  4  1  0\n  1 14  1  0\n  4  5  1  0\n  5  6  1  0\n  6  7  1  0\n  6  8  1  0\n  7 12  1  0\n  8  9  1  0\n  8 10  1  0\n 10 11  1  0\n 10 12  1  0\n 12 13  1  0\n 14 15  1  0\n 15 16  2  0\n 15 17  1  0\n 15 18  1  0\n 18 19  1  0\n 19 20  1  0\n 20 21  1  0\n 20 22  1  0\n 21 26  1  0\n 22 23  1  0\n 22 24  1  0\n 24 25  1  0\n 24 26  1  0\n 26 27  1  0\n 27 28  1  0\n 27 35  1  0\n 28 29  2  0\n 29 30  1  0\n 29 33  1  0\n 30 31  2  0\n 30 32  1  0\n 33 34  1  0\n 34 35  2  0\nM  CHG  2   3  -1  17  -1\nM  END\n'
            m.get(base_url + '/fragments?pdb_codes=3j7u', json=[{'pdb_code': '3j7u', 'mol': molblock}])
            m.get(base_url + '/fragments?pdb_codes=3wxm', json=[{'pdb_code': '3wxm', 'mol': molblock}])

            response = client.fragments_by_pdb_codes(pdb_codes=['3j7u', '3wxm'], chunk_size=1)

            assert isinstance(response[0]['mol'], Mol)
            assert isinstance(response[1]['mol'], Mol)
            del response[0]['mol']
            del response[1]['mol']
            expected = [{'pdb_code': '3j7u'}, {'pdb_code': '3wxm'}]
            assert response == expected

    def test_fragments_by_id_withmolisnone(self, base_url, client):
        with requests_mock.mock() as m:
            expected = [
                {'smiles': None,
                 'pdb_code': '3j7u',
                 'pdb_title': 'Catalase structure determined by electron crystallography of thin 3D crystals',
                 'atom_codes': 'PA,O1A,O2A,O5B,C5B,C4B,O4B,C3B,O3B,C2B,C1B,O3,PN,O1N,O2N,O5D,C5D,C4D,O4D,C3D,O3D,C2D,O2D,C1D,N1N,C2N,C3N,C7N,O7N,N7N,C4N,C5N,C6N',
                 'uniprot_acc': 'P00432',
                 'mol': None,
                 'prot_chain': 'A', 'het_seq_nr': 602, 'het_code': 'NDP', 'prot_name': 'Catalase',
                 'ec_number': '1.11.1.6', 'frag_nr': 24, 'frag_id': '3j7u_NDP_frag24', 'rowid': 7059,
                 'uniprot_name': 'Catalase', 'nr_r_groups': 2, 'het_chain': 'A', 'hash_code': '6ef5a609fb192dba'}
            ]
            url = base_url + '/fragments?fragment_ids=3j7u_NDP_frag24,3j7u_NDP_frag23'
            m.get(url, json=expected)

            response = client.fragments_by_id(fragment_ids=['3j7u_NDP_frag24', '3j7u_NDP_frag23'])

            assert response == expected

    def test_fragments_by_id_withsomenotfound(self, base_url, client):
        raise NotImplemented()
