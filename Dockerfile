FROM python:3-slim

COPY dockerbash /root/.bashrc


# Mailer needs access to an smtp server
# good would be to use host port 25 but how can I make it available in the guest?
ENV GPXITY_DISABLE_BACKENDS="Mailer"

RUN pip install --upgrade pip
RUN pip install --index-url https://test.pypi.org/pypi/ --extra-index-url https://pypi.org/simple gpxity pytest

COPY pytest.ini /usr/local/lib/python3.6/site-packages/gpxity

RUN cd /usr/local/lib/python3.6/site-packages/gpxity ; pytest -k 'not slow'
