(()=>{
  const token=location.hash.slice(1),button=document.getElementById('acknowledge'),status=document.getElementById('status');
  history.replaceState(null,'',location.pathname);
  if(!/^[A-Za-z0-9_-]{43}$/.test(token)){button.disabled=true;status.textContent='This activation link is invalid. Ask your captain for another email.';return;}
  button.onclick=async()=>{
    button.disabled=true;
    try{
      const response=await fetch('/api/auth/tournament-acknowledgement',{method:'POST',headers:{'Content-Type':'application/json','X-Dhoyo-Request':'1'},body:JSON.stringify({token})});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||'Unable to acknowledge participation.');
      status.textContent=result.message;button.textContent='Acknowledged';
    }catch(error){status.textContent=error.message;button.disabled=false;}
  };
})();
