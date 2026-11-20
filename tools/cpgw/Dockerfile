FROM alpine:3.22 AS download
RUN apk add --no-cache curl unzip \
    && curl --fail --show-error --silent --location --retry 3 \
       https://download2.interactivebrokers.com/portal/clientportal.gw.zip \
       --output /tmp/clientportal.gw.zip \
    && unzip -q /tmp/clientportal.gw.zip -d /cpgw

FROM eclipse-temurin:17-jre-jammy
WORKDIR /cpgw
COPY --from=download --chown=10001:10001 /cpgw/ /cpgw/
RUN groupadd --gid 10001 cpgw \
    && useradd --uid 10001 --gid cpgw --home-dir /cpgw --no-create-home cpgw \
    && mkdir -p /cpgw/logs \
    && chown cpgw:cpgw /cpgw /cpgw/logs
ENV HOME=/cpgw
USER 10001:10001
EXPOSE 5000
CMD ["/bin/bash", "bin/run.sh", "root/conf.yaml"]
