const HEIF_EXTENSIONS = ['.heic', '.heif']

export function isHeifPhoto(file) {
  const name = String(file?.name || '').toLowerCase()
  const type = String(file?.type || '').toLowerCase()
  return type === 'image/heic' || type === 'image/heif' || HEIF_EXTENSIONS.some((extension) => name.endsWith(extension))
}
