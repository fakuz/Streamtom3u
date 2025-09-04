#!/bin/bash
python3 -m pip install requests
python3 -m pip install requests
python3 -m pip install lxml
python3 -m pip install pytz
python3 -m pip install beautifulsoup4

python3 youtube_m3ugrabber.py > ./youtube.m3u

echo M3U update complete.
