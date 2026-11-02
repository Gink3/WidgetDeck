import {useEffect,useState} from 'react';
export function usePhone(query='(max-width:900px)') {
  const [phone,setPhone]=useState(()=>matchMedia(query).matches);
  useEffect(()=>{const media=matchMedia(query),update=()=>setPhone(media.matches);update();media.addEventListener('change',update);return()=>media.removeEventListener('change',update);},[query]);
  return phone;
}
