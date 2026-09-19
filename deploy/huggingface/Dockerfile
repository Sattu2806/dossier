# The dossier API, packaged for a free Hugging Face Space.
#
# It installs the published package straight from GitHub rather than copying
# source, so this Space repo stays two files and a rebuild always picks up
# the latest main.
FROM python:3.13-slim

# Spaces hardcode port 7860 and run the container as a non-root user.
ENV PORT=7860 \
    DOSSIER_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    DOSSIER_DATA_DIR=/tmp/chroma

RUN pip install --no-cache-dir \
    "dossier[postgres] @ git+https://github.com/Sattu2806/dossier@main"

EXPOSE 7860

CMD ["dossier", "serve"]
