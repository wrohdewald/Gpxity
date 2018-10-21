FROM python:3-slim

COPY dockerbash /root/.bashrc

RUN pip install --upgrade pip
RUN pip install --index-url https://test.pypi.org/pypi/ --extra-index-url https://pypi.org/simple gpxity pytest aiosmtpd

COPY pytest.ini /usr/local/lib/python3.6/site-packages/gpxity

# comment the next line if you want to run the tests manually

RUN cd /usr/local/lib/python3.6/site-packages/gpxity ; pytest -k 'not slow'
