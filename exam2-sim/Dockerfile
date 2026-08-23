FROM registry.access.redhat.com/ubi8/ubi:latest

ARG BUILDREPO=http://unreachable-internal-server.example.com/files/config.json

WORKDIR /app

RUN curl -sSL ${BUILDREPO} -o /app/config.json

COPY app.sh /app/app.sh
RUN chmod +x /app/app.sh

CMD ["/app/app.sh"]
