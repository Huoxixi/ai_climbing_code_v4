// Bundled samples do not need a second network request before upload.
export function photoSampleFile(dataUrl, name) {
  const match = /^data:(image\/jpeg);base64,([A-Za-z0-9+/=]+)$/.exec(dataUrl)
  if (!match) throw new Error('Invalid bundled photo sample')
  const bytes = Uint8Array.from(atob(match[2]), character => character.charCodeAt(0))
  return new File([bytes], `${name}.jpg`, { type:match[1] })
}
