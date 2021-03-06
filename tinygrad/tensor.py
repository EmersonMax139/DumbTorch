# inspired by https://github.com/karpathy/micrograd/blob/master/micrograd/engine.py
from functools import partialmethod
import numpy as np
from tinygrad.utils import im2col, col2im

# **** start with two base classes ****

class Tensor:
  def __init__(self, data):
    #print(type(data), data)
    if type(data) != np.ndarray:
      print("error constructing tensor with %r" % data)
      assert(False)
    if data.dtype == np.float64:
      #print("are you sure you want float64 in %r?" % data)
      pass
    self.data = data
    self.grad = None

    # internal variables used for autograd graph construction
    self._ctx = None

  def __repr__(self):
    return "Tensor %r with grad %r" % (self.data, self.grad)

  @property
  def shape(self):
    return self.data.shape

  @staticmethod
  def zeros(*shape):
    return Tensor(np.zeros(shape, dtype=np.float32))

  @staticmethod
  def randn(*shape):
    return Tensor(np.random.randn(*shape).astype(np.float32))

  def backward(self, allow_fill=True):
    #print("running backward on", self)
    if self._ctx is None:
      return

    if self.grad is None and allow_fill:
      # fill in the first grad with one
      # this is "implicit gradient creation"
      assert self.data.size == 1
      self.grad = np.ones_like(self.data)

    assert(self.grad is not None)

    grads = self._ctx.backward(self._ctx, self.grad)
    if len(self._ctx.parents) == 1:
      grads = [grads]
    for t,g in zip(self._ctx.parents, grads):
      if g is None:
        continue
      if g.shape != t.data.shape:
        print("grad shape must match tensor shape in %r, %r != %r" %
          (self._ctx, g.shape, t.data.shape))
        assert(False)
      t.grad = g
      t.backward(False)

  def mean(self):
    div = Tensor(np.array([1/self.data.size], dtype=self.data.dtype))
    return self.sum().mul(div)

# An instantiation of the Function is the Context
class Function:
  def __init__(self, *tensors):
    self.parents = tensors
    self.saved_tensors = []

  def save_for_backward(self, *x):
    self.saved_tensors.extend(x)

  # note that due to how partialmethod works, self and arg are switched
  def apply(self, arg, *x):
    # support the args in both orders
    if type(arg) == Tensor:
      op = self
      x = [arg]+list(x)
    else:
      op = arg
      x = [self]+list(x)
    ctx = op(*x)
    ret = Tensor(op.forward(ctx, *[t.data for t in x]))
    ret._ctx = ctx
    return ret

def register(name, fxn):
  setattr(Tensor, name, partialmethod(fxn.apply, fxn))

# **** implement a few functions ****

class Reshape(Function):
  @staticmethod
  def forward(ctx, x, shape):
    ctx.save_for_backward(x.shape)
    return x.reshape(shape)

  @staticmethod
  def backward(ctx, grad_output):
    in_shape, = ctx.saved_tensors
    return grad_output.reshape(in_shape), None
register('reshape', Reshape)

class Mul(Function):
  @staticmethod
  def forward(ctx, x, y):
    ctx.save_for_backward(x, y)
    return x*y

  @staticmethod
  def backward(ctx, grad_output):
    x,y = ctx.saved_tensors
    return y*grad_output, x*grad_output
register('mul', Mul)

class Add(Function):
  @staticmethod
  def forward(ctx, x, y):
    return x+y

  @staticmethod
  def backward(ctx, grad_output):
    return grad_output, grad_output
register('add', Add)
    
class ReLU(Function):
  @staticmethod
  def forward(ctx, input):
    ctx.save_for_backward(input)
    return np.maximum(input, 0)

  @staticmethod
  def backward(ctx, grad_output):
    input, = ctx.saved_tensors
    grad_input = grad_output.copy()
    grad_input[input < 0] = 0
    return grad_input
register('relu', ReLU)

class Dot(Function):
  @staticmethod
  def forward(ctx, input, weight):
    ctx.save_for_backward(input, weight)
    return input.dot(weight)

  @staticmethod
  def backward(ctx, grad_output):
    input, weight = ctx.saved_tensors
    grad_input = grad_output.dot(weight.T)
    grad_weight = grad_output.T.dot(input).T
    return grad_input, grad_weight
register('dot', Dot)

class Sum(Function):
  @staticmethod
  def forward(ctx, input):
    ctx.save_for_backward(input)
    return np.array([input.sum()])

  @staticmethod
  def backward(ctx, grad_output):
    input, = ctx.saved_tensors
    return grad_output * np.ones_like(input)
register('sum', Sum)

class LogSoftmax(Function):
  @staticmethod
  def forward(ctx, input):
    def logsumexp(x):
      #return np.log(np.exp(x).sum(axis=1))
      c = x.max(axis=1)
      return c + np.log(np.exp(x-c.reshape((-1, 1))).sum(axis=1))
    output = input - logsumexp(input).reshape((-1, 1))
    ctx.save_for_backward(output)
    return output

  @staticmethod
  def backward(ctx, grad_output):
    output, = ctx.saved_tensors
    return grad_output - np.exp(output)*grad_output.sum(axis=1).reshape((-1, 1))
register('logsoftmax', LogSoftmax)


class Conv2D(Function):
  @staticmethod
  def forward(ctx, x, w):
    cout,cin,H,W = w.shape
    tw = w.reshape(cout, -1).T
    bs,oy,ox = x.shape[0], x.shape[2]-(H-1), x.shape[3]-(W-1)

    ctx.save_for_backward(x, w)
    ret = np.zeros((bs, cout, oy, ox), dtype=w.dtype)
    for Y in range(oy):
      for X in range(ox):
        tx = x[:, :, Y:Y+H, X:X+W].reshape(bs, -1)
        ret[:, :, Y, X] = tx.dot(tw)
    return ret

  @staticmethod
  def backward(ctx, grad_output):
    bs,_,oy,ox = grad_output.shape
    x, w = ctx.saved_tensors
    cout,cin,H,W = w.shape
    tw = w.reshape(cout, -1)

    dx, dw = np.zeros_like(x), np.zeros_like(w)
    for Y in range(grad_output.shape[2]):
      for X in range(grad_output.shape[3]):
        gg = grad_output[:, :, Y, X]
        tx = x[:, :, Y:Y+H, X:X+W].reshape(x.shape[0], -1)
        dw += gg.T.dot(tx).reshape(dw.shape)
        dx[:, :, Y:Y+H, X:X+W] += gg.dot(tw).reshape(dx.shape[0], dx.shape[1], H, W)
    return dx, dw
#register('conv2d', Conv2D)

class FastConv2D(Function):
  @staticmethod
  def forward(ctx, x, w):
    cout,cin,H,W = w.shape
    tw = w.reshape(cout, -1).T
    bs,oy,ox = x.shape[0], x.shape[2]-(H-1), x.shape[3]-(W-1)

    # im2col
    tx = im2col(x, H, W)

    # save the im2col output (OMG it's bigger!)
    ctx.save_for_backward(tx, w)

    # now the conv is a GEMM
    ret = tx.dot(tw).reshape(oy, ox, bs, cout)

    # order correctly
    return np.moveaxis(ret, [0,1,2,3], [2,3,0,1])

  @staticmethod
  def backward(ctx, grad_output):
    bs,_,oy,ox = grad_output.shape
    tx, w = ctx.saved_tensors
    cout,cin,H,W = w.shape
    tw = w.reshape(w.shape[0], -1)

    # order correctly
    gg = np.moveaxis(grad_output, [0,1,2,3], [2,3,0,1]).reshape(-1, cout)

    # dw is easy
    dw = gg.T.dot(tx).reshape(w.shape)

    # dx is harder
    dxi = gg.dot(tw)

    # if we im2col on the forward, we col2im on the backward
    dx = col2im(dxi, H, W, oy+(H-1), ox+(W-1))

    return dx, dw
register('conv2d', FastConv2D)

