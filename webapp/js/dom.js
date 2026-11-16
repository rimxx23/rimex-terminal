export function el(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = options.text;
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) element.setAttribute(name, value);
  }
  if (options.onClick) element.addEventListener("click", options.onClick);
  element.append(...children);
  return element;
}

export function setField(root, name, text, level) {
  const element = root.querySelector(`[data-field="${name}"]`);
  element.textContent = text;
  if (level) element.classList.add(level);
  return element;
}
