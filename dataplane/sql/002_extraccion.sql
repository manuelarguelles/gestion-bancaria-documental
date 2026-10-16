-- Trazabilidad de la lectura: cómo se extrajo cada documento y qué campos no se pudieron verificar.
ALTER TABLE doc.documentos    ADD COLUMN IF NOT EXISTS metodo_extraccion text;
ALTER TABLE doc.documentos    ADD COLUMN IF NOT EXISTS confianza_ocr     numeric(5,2);
ALTER TABLE doc.documentos    ADD COLUMN IF NOT EXISTS notas_extraccion  jsonb NOT NULL DEFAULT '[]';
ALTER TABLE doc.cartas_fianza ADD COLUMN IF NOT EXISTS lectura_dudosa    text[] NOT NULL DEFAULT '{}';
