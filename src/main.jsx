import React from 'react';
import { createRoot } from 'react-dom/client';
import Flowground from './Flowground.jsx';
import './styles.css';

createRoot(document.getElementById('root')).render(
  <Flowground edgeStyle="curved" canvasTexture="dots" accent="#E8684A" />
);
