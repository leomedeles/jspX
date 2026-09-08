FROM nodered/node-red:4.1.0

# Install the nodes referenced by the tracked flow into the immutable image.
# package.json is the single source for the dashboard version.
COPY --chown=node-red:root package.json /tmp/jspx-package.json
RUN dashboard_version="$(node -p "require('/tmp/jspx-package.json').dependencies['node-red-dashboard']")" \
    && npm install --no-update-notifier --no-fund --omit=dev --no-save "node-red-dashboard@${dashboard_version}" \
    && rm /tmp/jspx-package.json
