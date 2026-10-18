// Immutable, same weights as the installed public app. Never accept model URLs
// or checksums from a user supplied query string or a remote manifest.
export const MODEL_VERSION = 'rtmw-l-384x288-cocktail14-20231122'
export const CACHE_NAME = 'climbing-browser-models-v1'
export const MODEL_FILES = [
  {name:'detector', file:'detector.onnx', bytes:35998962, sha256:'332e09ea9696e3401049b6c5314851db020b6430f85da159e65f37034ab3aee8'},
  {name:'pose', file:'rtmw.onnx', bytes:229320930, sha256:'bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054'},
].map(file => ({...file, url:`/browser-models/${MODEL_VERSION}/${file.file}`}))
