import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from prepare_tokenizer import prepare


class PreparationTests(unittest.TestCase):
    def test_downloads_only_pinned_assets_and_never_creates_calibration(self):
        raw = b'fixture asset'
        source = {'model_repository':'fixture/model', 'revision':'a'*40,
                  'files':{'tokenizer.json':{'sha256':hashlib.sha256(raw).hexdigest()}}}
        requests = []
        def fetch(url):
            requests.append(url)
            return raw
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)
            prepare(source, target, fetch)
            prepare(source, target, fetch)
            self.assertEqual(len(requests), 1)
            self.assertIn('/resolve/'+'a'*40+'/tokenizer.json', requests[0])
            self.assertFalse((target/'calibration.json').exists())

    def test_bad_download_or_existing_file_is_not_adopted_or_overwritten(self):
        source = {'model_repository':'fixture/model', 'revision':'a'*40,
                  'files':{'LICENSE':{'sha256':hashlib.sha256(b'valid').hexdigest()}}}
        with tempfile.TemporaryDirectory() as root:
            target = Path(root)
            with self.assertRaises(ValueError):
                prepare(source, target, lambda url:b'wrong')
            self.assertFalse((target/'LICENSE').exists())
            (target/'LICENSE').write_bytes(b'existing')
            with self.assertRaises(ValueError):
                prepare(source, target, lambda url:b'valid')
            self.assertEqual((target/'LICENSE').read_bytes(), b'existing')


if __name__ == '__main__': unittest.main()
