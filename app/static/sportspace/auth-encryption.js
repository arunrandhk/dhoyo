// Credential request bodies are encrypted before fetch, without changing forms.
// HTTPS remains required; a browser owner can inspect values before encryption.
async function encryptAccountPayload(path,payload){
  const local=['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname);
  if(location.protocol!=='https:'&&!(location.protocol==='http:'&&local))throw new Error('Use HTTPS before sending account details.');
  if(!window.crypto?.subtle)throw new Error('Your browser cannot encrypt account details. Use a current browser over HTTPS.');
  const supported=['login','register','change-password','request-password-code','reset-password-code','forgot-password','reset-password','activate-account','resend-activation','google','google/register','google/link'];
  if(!supported.includes(path))throw new Error('Unsupported account action.');
  const endpoint='/api/auth/'+path,encoder=new TextEncoder();
  const decode=value=>{
    if(typeof value!=='string'||!value||!/^[A-Za-z0-9_-]+$/.test(value))throw new Error('Invalid account encryption response.');
    const raw=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4));
    return Uint8Array.from(raw,char=>char.charCodeAt(0));
  };
  const encode=value=>{
    let raw='';for(const byte of new Uint8Array(value))raw+=String.fromCharCode(byte);
    return btoa(raw).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  };
  const response=await nativeFetch('/api/auth/encryption-key?path='+encodeURIComponent(endpoint),{method:'GET',cache:'no-store',headers:{'X-Dhoyo-Request':'1'},signal:AbortSignal.timeout(15000)});
  if(response.status===404)throw new Error('The running server is missing the encryption endpoint. Restart Flask from the updated app folder, then refresh this page.');
  const key=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(key?.error||'Could not prepare encrypted sign-in. Try again.');
  if(key?.v!==1||typeof key.kid!=='string'||!key.kid||decode(key.challengeId).length!==32||key.publicKey?.kty!=='EC'||key.publicKey?.crv!=='P-256'||decode(key.publicKey.x).length!==32||decode(key.publicKey.y).length!==32)throw new Error('Invalid account encryption response.');
  const subtle=window.crypto.subtle;
  const server=await subtle.importKey('jwk',{kty:'EC',crv:'P-256',x:key.publicKey.x,y:key.publicKey.y,ext:true},{name:'ECDH',namedCurve:'P-256'},false,[]);
  const client=await subtle.generateKey({name:'ECDH',namedCurve:'P-256'},false,['deriveBits']);
  const shared=await subtle.deriveBits({name:'ECDH',public:server},client.privateKey,256);
  const input=await subtle.importKey('raw',shared,'HKDF',false,['deriveKey']);
  const aes=await subtle.deriveKey({name:'HKDF',hash:'SHA-256',salt:decode(key.challengeId),info:encoder.encode('dhoyo-auth-request-v1')},input,{name:'AES-GCM',length:256},false,['encrypt']);
  const clear=encoder.encode(JSON.stringify(payload)),iv=window.crypto.getRandomValues(new Uint8Array(12));
  try{
    const encrypted=await subtle.encrypt({name:'AES-GCM',iv,additionalData:encoder.encode('dhoyo-auth-v1|'+endpoint+'|'+key.kid+'|'+key.challengeId),tagLength:128},aes,clear);
    return {v:1,kid:key.kid,challengeId:key.challengeId,epk:encode(await subtle.exportKey('raw',client.publicKey)),iv:encode(iv),ciphertext:encode(encrypted)};
  }finally{clear.fill(0);new Uint8Array(shared).fill(0);}
}
