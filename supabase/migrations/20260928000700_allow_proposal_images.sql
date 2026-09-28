-- Allow the private proposal request bucket to store visual evidence.
update storage.buckets as bucket
set allowed_mime_types = (
  select array_agg(distinct mime_type)
  from unnest(
    coalesce(bucket.allowed_mime_types, array[]::text[])
    || array['image/jpeg', 'image/png', 'image/webp']::text[]
  ) as allowed(mime_type)
)
where bucket.id = 'proposal-documents';
