"""Lossless cropped, row-major RLE for offline instance-model comparisons."""
import cv2
import numpy as np


def encode_mask(mask, origin=(0, 0)):
    binary=(mask>0).astype(np.uint8)
    x,y,w,h=cv2.boundingRect(binary)
    if not w or not h: raise ValueError('实例掩膜为空')
    flat=binary[y:y+h,x:x+w].ravel()
    changes=np.flatnonzero(np.diff(flat))+1
    counts=np.diff(np.r_[0,changes,len(flat)]).astype(int).tolist()
    if flat[0]: counts.insert(0,0)
    return {'encoding':'row-major-rle-v1','origin':[int(origin[0]+x),int(origin[1]+y)],
            'size':[h,w],'counts':counts}


def decode_mask(data, shape):
    if data.get('encoding')!='row-major-rle-v1': raise ValueError('未知掩膜编码')
    origin=data.get('origin',[]);size=data.get('size',[]);counts=data.get('counts',[])
    if len(origin)!=2 or len(size)!=2 or not counts:
        raise ValueError('掩膜尺寸或计数缺失')
    if any(type(v) is not int or v<0 for v in origin+size+counts):
        raise ValueError('掩膜坐标和计数必须为非负整数')
    x,y=origin;h,w=size
    if not h or not w or x+w>shape[1] or y+h>shape[0] or sum(counts)!=h*w or len(counts)>h*w+1:
        raise ValueError('掩膜超出原图范围或计数错误')
    flat=np.repeat(np.arange(len(counts),dtype=np.uint8)%2,counts).reshape(h,w)
    if not flat.any(): raise ValueError('实例掩膜为空')
    result=np.zeros(shape,np.uint8);result[y:y+h,x:x+w]=flat
    return result
