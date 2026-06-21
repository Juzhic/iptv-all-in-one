const fs = require('fs');
const path = require('path');

const patchTargets = [
  {
    file: 'node_modules/tdesign-icons-vue-next/esm/svg-sprite/svg-sprite.js',
    search: 'https://tdesign.gtimg.com/icon/0.4.2/fonts/index.js',
    replace: '/tdesign-icons/index.js',
  },
  {
    file: 'node_modules/tdesign-icons-vue-next/esm/iconfont/icon.js',
    search: 'https://tdesign.gtimg.com/icon/0.4.2/fonts/index.css',
    replace: '/tdesign-icons/index.css',
  },
  {
    file: 'node_modules/tdesign-icons-vue-next/lib/svg-sprite/svg-sprite.js',
    search: 'https://tdesign.gtimg.com/icon/0.4.2/fonts/index.js',
    replace: '/tdesign-icons/index.js',
  },
  {
    file: 'node_modules/tdesign-icons-vue-next/lib/iconfont/icon.js',
    search: 'https://tdesign.gtimg.com/icon/0.4.2/fonts/index.css',
    replace: '/tdesign-icons/index.css',
  },
];

let patched = 0;
for (const { file, search, replace } of patchTargets) {
  const filePath = path.resolve(__dirname, '..', file);
  if (!fs.existsSync(filePath)) continue;
  let content = fs.readFileSync(filePath, 'utf8');
  if (!content.includes(search)) continue;
  content = content.replace(new RegExp(search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), replace);
  fs.writeFileSync(filePath, content, 'utf8');
  patched++;
}

if (patched > 0) {
  console.log(`[postinstall] Patched tdesign-icons-vue-next: ${patched} file(s) updated to use local icon assets`);
}
