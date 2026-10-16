-- Data plane de Gestión Bancaria Documental. Idempotente.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS doc;

CREATE TABLE IF NOT EXISTS doc.corridas (
  id            uuid PRIMARY KEY,
  fecha_corte   date        NOT NULL,
  creado_en     timestamptz NOT NULL DEFAULT now(),
  resumen       jsonb
);

CREATE TABLE IF NOT EXISTS doc.documentos (
  id            bigserial PRIMARY KEY,
  archivo       text        NOT NULL,
  sha256        text        NOT NULL UNIQUE,
  tipo          text        NOT NULL,            -- carta_fianza | liberacion_garantia | otro
  clasificacion jsonb       NOT NULL,
  texto         text        NOT NULL,
  estado        text        NOT NULL DEFAULT 'PROCESADO',
  creado_en     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc.cartas_fianza (
  id                 bigserial PRIMARY KEY,
  documento_id       bigint  NOT NULL UNIQUE REFERENCES doc.documentos(id),
  numero             text    NOT NULL,
  ordenante          text    NOT NULL,
  beneficiario       text    NOT NULL,
  monto              numeric(14,2) NOT NULL,
  moneda             char(3) NOT NULL,
  fecha_emision      date,
  fecha_vencimiento  date    NOT NULL,
  tipo_garantia      text
);
CREATE INDEX IF NOT EXISTS ix_cartas_numero ON doc.cartas_fianza (numero);

CREATE TABLE IF NOT EXISTS doc.registro_tesoreria (
  numero             text PRIMARY KEY,
  ordenante          text    NOT NULL,
  beneficiario       text    NOT NULL,
  monto              numeric(14,2) NOT NULL,
  moneda             char(3) NOT NULL,
  fecha_vencimiento  date    NOT NULL,
  estado_registro    text    NOT NULL DEFAULT 'VIGENTE'
);

CREATE TABLE IF NOT EXISTS doc.conciliacion (
  id            bigserial PRIMARY KEY,
  corrida_id    uuid    NOT NULL REFERENCES doc.corridas(id),
  numero        text    NOT NULL,
  carta_id      bigint  REFERENCES doc.cartas_fianza(id),
  resultado     text    NOT NULL,                -- CONCILIADA | ALERTA | EXCEPCION
  codigos       text[]  NOT NULL DEFAULT '{}',
  detalle       jsonb   NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_conc_corrida ON doc.conciliacion (corrida_id);

CREATE TABLE IF NOT EXISTS doc.excepciones (
  id                 bigserial PRIMARY KEY,
  conciliacion_id    bigint NOT NULL UNIQUE REFERENCES doc.conciliacion(id),
  explicacion        text   NOT NULL,
  accion_recomendada text   NOT NULL,
  prioridad          text   NOT NULL,            -- ALTA | MEDIA | BAJA
  politicas_citadas  text[] NOT NULL DEFAULT '{}',
  estado             text   NOT NULL DEFAULT 'PENDIENTE',  -- PENDIENTE | APROBADA | RECHAZADA | ESCALADA
  revisor            text,
  comentario         text,
  resuelto_en        timestamptz
);

CREATE TABLE IF NOT EXISTS doc.politicas (
  codigo      text PRIMARY KEY,
  titulo      text NOT NULL,
  contenido   text NOT NULL,
  embedding   vector(1536)
);
CREATE INDEX IF NOT EXISTS ix_politicas_hnsw ON doc.politicas USING hnsw (embedding vector_cosine_ops);

-- Rol de solo lectura para el canal de consulta (agencias): sin acceso a texto de documentos.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gbd_lector') THEN
    CREATE ROLE gbd_lector NOLOGIN;
  END IF;
END $$;
GRANT USAGE ON SCHEMA doc TO gbd_lector;
GRANT SELECT ON doc.cartas_fianza, doc.registro_tesoreria, doc.conciliacion, doc.excepciones TO gbd_lector;
