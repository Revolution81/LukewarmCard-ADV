# Build environment for LukewarmCard ADV (COLDCARD firmware on the Cardputer ADV): ESP-IDF v5.5.4 plus
# what the desktop tests need. Usage (BUILDING.md has the details):
#
#   docker build -t lukewarmcard .
#   docker run --rm -v "$PWD:/port" lukewarmcard latest-mk5
#
# Images land in ./dist/ on your computer.
FROM espressif/idf:v5.5.4

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libffi-dev pkg-config git \
 && rm -rf /var/lib/apt/lists/*

# test tools: embit checks signatures, HWI is the library Sparrow uses
# (HWI 3.2.0 declares Python < 3.13; it runs fine on newer)
RUN . "$IDF_PATH/export.sh" >/dev/null \
 && pip install --no-cache-dir embit pillow ckcc-protocol \
 && pip install --no-cache-dir --ignore-requires-python hwi==3.2.0

RUN git config --global --add safe.directory '*'

# sources are cached in the container's /src; mount a volume there to keep
# them between runs:  -v cc-src:/src
ENV SRC=/src
WORKDIR /port
ENTRYPOINT ["/bin/bash", "-c", ". \"$IDF_PATH/export.sh\" >/dev/null && exec tools/build_release.sh \"$@\"", "--"]
CMD ["latest-mk5"]
