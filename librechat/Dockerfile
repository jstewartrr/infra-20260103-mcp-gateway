FROM ghcr.io/danny-avila/librechat:latest

# Install curl if not present
USER root
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Create startup script that downloads config
RUN echo '#!/bin/sh\n\
curl -sL https://raw.githubusercontent.com/jstewartrr/sm-mcp-gateway/main/librechat/librechat.yaml -o /app/librechat.yaml\n\
exec npm start' > /app/start.sh && chmod +x /app/start.sh

# Set config path
ENV CONFIG_PATH=/app/librechat.yaml

# Use the custom start script
CMD ["/app/start.sh"]
