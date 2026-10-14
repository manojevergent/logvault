# Dev-oriented image. Compose mounts the source and runs `npm run dev`.
# For production, `next build` (output: "standalone") emits .next/standalone;
# a multi-stage prod target is added in Phase 6.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching. node_modules is preserved across the
# bind mount via an anonymous volume in docker-compose.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
