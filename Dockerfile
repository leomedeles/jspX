FROM rust:1.98.1-bookworm AS build
WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY fixtures ./fixtures
COPY web ./web
RUN rustup component add rustfmt clippy \
    && cargo fmt --all -- --check \
    && cargo clippy --all-targets -- -D warnings \
    && cargo test \
    && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home jspx \
    && mkdir /data && chown jspx:jspx /data
COPY --from=build /app/target/release/jspx /usr/local/bin/jspx
USER jspx
ENV JSPX_BIND=0.0.0.0:8080 JSPX_DB=/data/history.redb
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8080/health/ready || exit 1
CMD ["jspx"]
