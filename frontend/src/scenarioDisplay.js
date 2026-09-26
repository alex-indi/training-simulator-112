export function compactObjectName(name = '') {
  const legalForms = [
    [/^Государственное\s+автономное\s+научное\s+учреждение\s+города\s+Москвы\s*/i, 'ГАНУ г. Москвы '],
    [/^Государственное\s+автономное\s+образовательное\s+учреждение\s+города\s+Москвы\s*/i, 'ГАОУ г. Москвы '],
    [/^Государственное\s+бюджетное\s+образовательное\s+учреждение\s+города\s+Москвы\s*/i, 'ГБОУ г. Москвы '],
  ]
  const source = name.trim()
  const [pattern, abbreviation] = legalForms.find(([candidate]) => candidate.test(source)) || []
  const suffix = pattern ? source.replace(pattern, '').trim() : source
  const displaySuffix = suffix && !/^[«"]/.test(suffix)
    ? suffix.charAt(0).toLocaleUpperCase('ru') + suffix.slice(1)
    : suffix
  const compact = pattern ? `${abbreviation}${displaySuffix}`.trim() : displaySuffix

  if (!compact) return name.trim()
  return compact.charAt(0).toLocaleUpperCase('ru') + compact.slice(1)
}

export function compactInstanceName(instance) {
  const objectName = instance?.object_snapshot?.name || ''
  const templateName = instance?.template_snapshot?.name

  if (templateName) return templateName
  if (objectName && instance?.name?.endsWith(objectName)) {
    return instance.name.slice(0, -objectName.length).replace(/\s+[—-]\s*$/, '').trim()
  }
  return instance?.name || ''
}
