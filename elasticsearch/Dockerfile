# Based on the official image, installing the IK Chinese analyzer plugin pinned to the ES version.
# If the plugin download fails or IK is not needed, switch the es service in docker-compose from
# build to image: docker.elastic.co/elasticsearch/elasticsearch:8.15.0 (es.py falls back to standard).
ARG ES_VERSION=8.15.0
FROM docker.elastic.co/elasticsearch/elasticsearch:${ES_VERSION}

RUN elasticsearch-plugin install --batch \
    https://github.com/infinilabs/analysis-ik/releases/download/v${ES_VERSION}/elasticsearch-analysis-ik-${ES_VERSION}.zip
