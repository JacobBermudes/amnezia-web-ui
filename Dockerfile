FROM golang:1.25.5-alpine AS go-builder
WORKDIR /src

COPY go-monitor/ .
RUN go mod tidy && \
    CGO_ENABLED=0 GOOS=linux go build -o /awg-monitor main.go

FROM amneziavpn/amneziawg-go:latest

RUN apk update && apk add \
    python3 \
    py3-pip \
    nginx \
    supervisor \
    curl \
    apache2-utils \
    certbot \
    certbot-nginx \
    iptables-legacy \
    && rm -rf /var/cache/apk/*

RUN pip3 install flask flask_socketio flask-wtf requests python-socketio eventlet --break-system-packages

RUN mkdir -p /app/web-ui /var/log/supervisor /var/log/webui /var/log/amnezia /var/log/nginx /etc/amnezia/amneziawg /etc/letsencrypt /var/www/le

COPY web-ui /app/web-ui/

COPY --from=go-builder /awg-monitor /app/awg-monitor
RUN chmod +x /app/awg-monitor

RUN mkdir -p /run/nginx
COPY config/nginx/ /etc/nginx/http.d/
COPY config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY config/cli.ini /etc/letsencrypt/cli.ini

COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh

# Expose default ports
EXPOSE 80
EXPOSE 51340/udp

ENV NGINX_PORT=80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:$NGINX_PORT/status || exit 1

ENTRYPOINT ["/app/scripts/start.sh"]