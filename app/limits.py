"""Bound multipart transport size before Starlette spools an unbounded body."""
from starlette.responses import JSONResponse
class BodyLimit:
 def __init__(self,app):self.app=app
 async def __call__(self,scope,receive,send):
  if scope['type']!='http' or scope['path']!='/documents':return await self.app(scope,receive,send)
  limit=25*1024*1024+65536;total=0
  headers=dict(scope.get('headers',[]))
  try:
   if int(headers.get(b'content-length',b'0'))>limit:return await JSONResponse({'detail':{'status':'unsupported','code':'multipart_body_limit'}},status_code=413)(scope,receive,send)
  except ValueError:return await JSONResponse({'detail':{'status':'unsupported','code':'invalid_content_length'}},status_code=400)(scope,receive,send)
  async def bounded():
   nonlocal total
   msg=await receive();total+=len(msg.get('body',b''))
   if total>limit:raise BodyTooLarge()
   return msg
  try:await self.app(scope,bounded,send)
  except BodyTooLarge:await JSONResponse({'detail':{'status':'unsupported','code':'multipart_body_limit'}},status_code=413)(scope,receive,send)
class BodyTooLarge(Exception):pass
