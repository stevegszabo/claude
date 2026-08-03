FROM python:3.13-alpine

COPY unseal.py /usr/local/bin/unseal.py
RUN chmod +x /usr/local/bin/unseal.py

ENTRYPOINT ["python3", "/usr/local/bin/unseal.py"]
