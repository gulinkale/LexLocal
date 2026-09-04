ALTER TABLE chunks
ADD COLUMN source_start_offset INTEGER NOT NULL
CHECK (source_start_offset >= 0);

ALTER TABLE chunks
ADD COLUMN source_end_offset INTEGER NOT NULL
CHECK (source_end_offset > source_start_offset);
