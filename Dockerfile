# Ticket triage as a Functions container (Project 7, D28). The base is Microsoft's Functions image for Python 3.13,
# pinned by digest: scripts/pin_base_image.py rewrites the FROM line. Built and scanned by CI (the image job).
FROM mcr.microsoft.com/azure-functions/python:4-python3.13@sha256:9ebf4f388230a0a7d6515ee4b5bdc4371484bf89eaf566c59ed80dd6f6671ff3

# The host listens on 8080 (the container runs as a user that can't bind 80) and logs to the console.
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    ASPNETCORE_URLS=http://+:8080 \
    PORT=8080

# Python 3.13 workers load an app's packages from .python_packages only (dependency isolation). Installed
# anywhere else, some packages make the worker exit with 139 (azure-functions-python-worker issue 1797).
COPY src/requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check --target /home/site/wwwroot/.python_packages/lib/site-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY src/ /home/site/wwwroot/
# Lab tools for a laptop cluster (stdlib Python, D30): only the chart's lab profile starts them.
COPY scripts/fake_llm.py scripts/eventgrid_stub.py /opt/triage-lab/

# A fixed non-root user (Pod Security "restricted" needs a numeric uid). It owns the directories the host writes
# to, not the code.
RUN groupadd --gid 10001 triage \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /home --shell /usr/sbin/nologin triage \
    && mkdir -p /local /tmp/metrics \
    && chown 10001:10001 /home /local /tmp/metrics
USER 10001:10001
EXPOSE 8080
LABEL org.opencontainers.image.source=https://github.com/salmanamn/ticket-triage-agent \
    org.opencontainers.image.description="Support-ticket triage agent (Azure Functions, Python 3.13)" \
    org.opencontainers.image.licenses=MIT