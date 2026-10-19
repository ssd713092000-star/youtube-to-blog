# tube2dev-web: Next.js standalone server.
# NEXT_PUBLIC_* values are inlined at build time, so pass them as build args per environment.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_AUTH_MODE=firebase
ARG NEXT_PUBLIC_RELEASE=dev
ARG NEXT_PUBLIC_FIREBASE_API_KEY=""
ARG NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=""
ARG NEXT_PUBLIC_FIREBASE_PROJECT_ID=""
ARG NEXT_PUBLIC_FIREBASE_APP_ID=""
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_AUTH_MODE=$NEXT_PUBLIC_AUTH_MODE \
    NEXT_PUBLIC_RELEASE=$NEXT_PUBLIC_RELEASE \
    NEXT_PUBLIC_FIREBASE_API_KEY=$NEXT_PUBLIC_FIREBASE_API_KEY \
    NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=$NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN \
    NEXT_PUBLIC_FIREBASE_PROJECT_ID=$NEXT_PUBLIC_FIREBASE_PROJECT_ID \
    NEXT_PUBLIC_FIREBASE_APP_ID=$NEXT_PUBLIC_FIREBASE_APP_ID
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npx tsc --noEmit && npx vitest run && npx next build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=8080 HOSTNAME=0.0.0.0
RUN addgroup -g 10001 app && adduser -u 10001 -G app -D app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 8080
CMD ["node", "server.js"]
