FROM python:3-slim

COPY dockerbash /root/.bashrc

RUN pip install pytest  gpxity

RUN pytest -v /usr/local/lib/python3.6/site-packages/gpxity

