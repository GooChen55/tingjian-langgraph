const path=require('node:path');
const {spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
process.env.UNI_INPUT_DIR=root;
process.env.UNI_OUTPUT_DIR=path.join(root,'dist','h5');
const bin=path.join(path.dirname(require.resolve('@dcloudio/vite-plugin-uni/package.json')),'bin','uni.js');
const result=spawnSync(process.execPath,[bin,'build','-p','h5'],{cwd:root,env:process.env,stdio:'inherit'});
process.exit(result.status??1);
