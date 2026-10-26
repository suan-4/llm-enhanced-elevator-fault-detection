import { describe, expect, it } from 'vitest'
import { editText } from './inputEditing'

describe('keyboard editing', () => {
  it('inserts in the middle and replaces only selected text', () => {
    expect(editText('制动正常', 2, 2, '器', false)).toEqual({ value: '制动器正常', cursor: 3 })
    expect(editText('制动正常', 2, 4, '异常', false).value).toBe('制动异常')
  })
  it('deletes a full emoji and a combined character', () => {
    expect(editText('A😀B', 3, 3, '', true)).toEqual({ value: 'AB', cursor: 1 })
    expect(editText('e\u0301', 2, 2, '', true).value).toBe('')
  })
  it('does not split surrogate pairs at maxlength', () => {
    expect(editText('A', 1, 1, '😀B', false, 2).value).toBe('A')
    expect(editText('ABC', 1, 2, 'xy', false, 3).value).toBe('AxC')
  })
  it('keeps numeric inputs valid and rejects words', () => {
    expect(editText('1', 1, 1, '电梯', false, -1, true).value).toBe('1')
    expect(editText('1', 1, 1, '.5', false, -1, true).value).toBe('1.5')
    expect(editText('1.5', 3, 3, '.', false, -1, true).value).toBe('1.5')
  })
})
