#!/bin/bash

set -o errexit
set -o pipefail

source /app/virtual/bin/activate

GUNICORN_BIND=${ADMISSION_BIND-127.0.0.1:8443}
GUNICORN_WORKERS=${ADMISSION_WORKERS-1}
GUNICORN_THREADS=${ADMISSION_THREADS-50}
GUNICORN_TIMEOUT=${ADMISSION_TIMEOUT-15}
GUNICORN_KEEP_ALIVE=${ADMISSION_KEEP_ALIVE-15}
GUNICORN_LOG_LEVEL=${ADMISSION_LOG_LEVEL-info}
GUNICORN_CRT=${ADMISSION_CRT-/app/ssl/admission.cloudserv.ca/admission.cloudserv.ca.crt}
GUNICORN_KEY=${ADMISSION_KEY-/app/ssl/admission.cloudserv.ca/admission.cloudserv.ca.key}

gunicorn \
--worker-class=gevent \
--workers=$GUNICORN_WORKERS \
--threads=$GUNICORN_THREADS \
--timeout=$GUNICORN_TIMEOUT \
--keep-alive=$GUNICORN_KEEP_ALIVE \
--bind=$GUNICORN_BIND \
--log-level=$GUNICORN_LOG_LEVEL \
--certfile=$GUNICORN_CRT \
--keyfile=$GUNICORN_KEY \
--access-logfile=- \
--error-logfile=- \
app.admission:controller

exit 0
