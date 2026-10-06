ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        ca-certificates \
        debhelper \
        dh-virtualenv \
        python3.10 \
        python3.10-dev \
        python3.10-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build/src

# dpkg-buildpackage writes its archives to the parent of the source directory.
# The runtime builder uses the caller's UID, so that parent must be writable.
RUN chmod 1777 /build

# Some locally cached Ubuntu-derived builder images carry an inherited
# /bin/bash entrypoint.  The package script supplies its own command.
ENTRYPOINT []
