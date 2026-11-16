// Schwarze Icons als PNG (512 px, transparent) für Sticker und Wallpaper.
// Aufruf: node icons.js <ausgabeordner>   (react, react-dom, react-icons und sharp liegen global über NODE_PATH)
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const md = require('react-icons/md');
const gi = require('react-icons/gi');
const sharp = require('sharp');

const out = process.argv[2];
const icons = {
  laden: md.MdShoppingCart,
  baecker: md.MdBakeryDining,
  tanke: md.MdLocalGasStation,
  automat: gi.GiVendingMachine,
  imbiss: md.MdLunchDining,
  rad: md.MdBuild,
  umweg: md.MdTurnRight,
  schlaf: md.MdHotel,
};

(async () => {
  for (const [name, Comp] of Object.entries(icons)) {
    let svg = renderToStaticMarkup(React.createElement(Comp, { size: 512 })).replace(/currentColor/g, '#000000');
    if (!svg.includes('xmlns=')) svg = svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
    await sharp(Buffer.from(svg), { density: 300 }).resize(512, 512).png().toFile(`${out}/${name}.png`);
  }
  console.log('Icons:', Object.keys(icons).join(', '));
})();
