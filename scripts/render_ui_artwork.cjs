// Export the editable SVG masters. Usage: node scripts/render_ui_artwork.cjs [sharp module path]
const fs=require('node:fs/promises');
const path=require('node:path');
const sharp=require(process.argv[2] || 'sharp');
const root=path.resolve(__dirname,'..');
(async()=>{
 const dir=path.join(root,'assets/design/slate/icons');
 const icons=JSON.parse(await fs.readFile(path.join(dir,'manifest.json'),'utf8'));
 for(const [target,name] of Object.entries(icons)){
  let svg=await fs.readFile(path.join(dir,name+'.svg'),'utf8');
  svg=svg.replaceAll('currentColor','#ffffff').replace('stroke-width="2"','stroke-width="1.7"');
  await sharp(Buffer.from(svg),{density:384}).resize(128,128).png().toFile(path.join(root,'carveracontroller',target));
 }
 const manifestPath=path.join(root,'assets/design/slate/artwork-manifest.json');
 try{
  const drawings=JSON.parse(await fs.readFile(manifestPath,'utf8'));
  for(const entry of drawings){
   let drawing=await fs.readFile(path.join(root,entry.source),'utf8');
   if(entry.mode==='selector')drawing=drawing.replace('<g id="detail">','<g id="detail" opacity="0">');
   await sharp(Buffer.from(drawing),{density:144}).resize(entry.width,entry.height).png().toFile(path.join(root,entry.target));
  }
 }catch(error){if(error.code!=='ENOENT')throw error;}
 console.log('Exported '+Object.keys(icons).length+' interface icons');
})().catch(error=>{console.error(error);process.exitCode=1;});
