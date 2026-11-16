"""Fetch cited public evaluation images; verify exact downloaded bytes.

Run from any directory: python3 fetch_images.py
Screenshots are intentionally not embedded in the distributed research report.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'benchmark.json').read_text(encoding='utf-8'))
ALLOWED = {'img.chuapp.com', 'q7.itc.cn', 'q6.itc.cn', 'q5.itc.cn', 'q4.itc.cn', 'q3.itc.cn',
           'img-tc.tapimg.com', 'img2-tc.tapimg.com', 'img2.tapimg.com', 'video2.tapimg.com', 'video3.tapimg.com'}


def main():
    failed = []
    for sample in MANIFEST['samples']:
        target = (ROOT / sample['file']).resolve()
        if not target.is_relative_to(ROOT / 'images'):
            raise ValueError('Image target must stay in images/')
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == sample['image_sha256']:
            print(sample['id'], 'cached')
            continue
        try:
            url = sample['source_image_url']
            if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in ALLOWED:
                raise ValueError('Unrecognized public image host; review the manifest before extending ALLOWED')
            request = Request(url, headers={'User-Agent': 'JCC-Research-Evaluation/0.1', 'Referer': sample['source_url']})
            with urlopen(request, timeout=30) as response:
                if urlsplit(response.geturl()).hostname not in ALLOWED:
                    raise ValueError('Unexpected redirected host')
                raw = response.read(20 * 1024 * 1024 + 1)
            if len(raw) > 20 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != sample['image_sha256']:
                raise ValueError('Image exceeds size limit or source bytes have changed')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            print(sample['id'], 'downloaded')
        except Exception as exc:
            failed.append(sample['id'])
            print(sample['id'], type(exc).__name__, str(exc))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
