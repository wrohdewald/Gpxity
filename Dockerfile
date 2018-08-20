FROM python:3-slim

COPY dockerbash /root/.bashrc

COPY pytest.ini /usr/local/lib/python3.6/site-packages/gpxity

# Mailer needs access to an smtp server
# good would be to use host port 25 but how can I make it available in the guest?
ENV GPXITY_DISABLE_BACKENDS="Mailer"

RUN pip install pytest gpxity

RUN cd /usr/local/lib/python3.6/site-packages/gpxity ; pytest
