# Multi-stage build for Next.js standalone output
# Stage 1: Install dependencies
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: Build the application
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next.config.ts evaluates `rewrites()` at build time and bakes the
# destination URL into .next/standalone, so the /api/* proxy target
# has to be set as a build ARG (not a runtime env var). Production
# leaves it unset; the web container runs in host networking and the
# default `http://localhost:{{api_port}}` from next.config.ts reaches
# the api container on the host. Ephemeral compose passes
# API_URL=http://api:{{api_port}} (bridge networking).
ARG API_URL
ENV API_URL=$API_URL
RUN npm run build

# Stage 3: Production runner
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy standalone output + static assets
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE {{web_port}}
ENV PORT={{web_port}}
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
