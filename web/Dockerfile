# Next.js in three stages: install, build, run. The runtime image carries the
# standalone output only — no node_modules, no source, no build toolchain.
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# DOSSIER_API_URL is read at request time by server components and the proxy
# route, so it is NOT needed here — which is what keeps this image portable
# between environments.
RUN npm run build


FROM node:24-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup -g 10001 nextjs && adduser -u 10001 -G nextjs -S nextjs

# `output: "standalone"` puts the server and its real dependencies here;
# static assets are copied separately because the standalone tracer does not
# include them.
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://127.0.0.1:'+process.env.PORT+'/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
