# 基于官方镜像，安装与 ES 版本严格一致的 IK 中文分词插件
# 若插件下载失败或不需要 IK，可直接把 docker-compose 中 es 的 build 改为
# image: docker.elastic.co/elasticsearch/elasticsearch:8.15.0（es.py 会自动回退 standard 分词）
ARG ES_VERSION=8.15.0
FROM docker.elastic.co/elasticsearch/elasticsearch:${ES_VERSION}

RUN elasticsearch-plugin install --batch \
    https://github.com/infinilabs/analysis-ik/releases/download/v${ES_VERSION}/elasticsearch-analysis-ik-${ES_VERSION}.zip
