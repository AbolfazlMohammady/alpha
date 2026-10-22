FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client openssl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies with the same simple
# pip configuration used by the Paya project.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir \
    --retries 5 \
    --timeout 60 \
    --trusted-host pypi.org \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org \
    -r /app/requirements.txt

# Pre-download the rembg ISNet model at image build time.
# This prevents the first customer upload from triggering a 179 MB download.
RUN python -c "from rembg import new_session; new_session('isnet-general-use')"

COPY . /app

RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
