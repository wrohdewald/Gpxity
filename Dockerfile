FROM python:3

RUN pip install --upgrade pip
RUN pip install --no-cache-dir pytest

WORKDIR /usr/src/Gpxity

COPY dockerbash /root/.bashrc

RUN pip install --upgrade --no-cache-dir gpxity

RUN pytest -v /usr/local/lib/python3.6/site-packages/gpxity

