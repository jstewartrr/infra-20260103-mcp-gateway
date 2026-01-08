FROM ghcr.io/danny-avila/librechat:latest

# Install curl (Alpine-based image uses apk)
USER root
RUN apk add --no-cache curl

# Create startup script that downloads config
RUN printf '#!/bin/sh\ncurl -sL https://raw.githubusercontent.com/jstewartrr/sm-mcp-gateway/main/librechat/librechat.yaml -o /app/librechat.yaml\nexec npm start\n' > /app/start.sh && chmod +x /app/start.sh

# Set config path
ENV CONFIG_PATH=/app/librechat.yaml

# Use the custom start script
CMD ["/bin/sh", "/app/start.sh"]
