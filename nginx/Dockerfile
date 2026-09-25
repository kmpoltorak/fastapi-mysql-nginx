FROM nginx
COPY fastapi.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 selfsigned-cert.sh /docker-entrypoint.d/10-selfsigned-cert.sh
