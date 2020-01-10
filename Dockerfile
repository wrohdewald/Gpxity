FROM python:3-slim

COPY dockerbash /root/.bashrc

RUN pip install --upgrade pip
RUN pip install --index-url https://test.pypi.org/pypi/ --extra-index-url https://pypi.org/simple gpxity pytest aiosmtpd

COPY pytest.ini /usr/local/lib/python3.8/site-packages/gpxity

# create dockeraccounts by copying dockeraccounts.template
# and inserting your own credentials

COPY dockeraccounts /usr/local/lib/python3.8/site-packages/gpxity/backends/test/test_accounts

# comment the next line if you want to run the tests manually

RUN cd /usr/local/lib/python3.8/site-packages/gpxity ; GPXITY_DISABLE_BACKENDS="MMT GPSIES Openrunner" pytest
